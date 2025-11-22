import bcrypt from 'bcryptjs';
import jwt from 'jsonwebtoken';
import userModel from '../models/userModel.js';
import transporter from '../config/nodemailer.js';
import { EMAIL_VERIFY_TEMPLATE, PASSWORD_RESET_TEMPLATE } from '../config/emailTemplates.js';

export const register = async(req, res)=>{
    const {name, email, password} = req.body;

    if(!name || !email || !password){
        return res.json({success: false, message: 'Missing Details'})
    }

    try {
        
        const existingUser = await userModel.findOne({email})

        if(existingUser){
            return res.json({success: false, message: "User already exists"});
        }

        const hashedPassword = await bcrypt.hash(password, 10);

        const user = new userModel({name, email, password: hashedPassword});
        await user.save();

        const token = jwt.sign({id: user._id}, process.env.JWT_SECRET, {expiresIn: '7d'}); //7 days

        res.cookie('token', token, {
            httpOnly: true, //only http can access this cookie
            secure: process.env.NODE_ENV === 'production',
            sameSite: process.env.NODE_ENV === 'production' ? 'none' : 'strict',
            maxAge: 7*24*60*60*1000 //expiry time in milliseconds (converted from 7 days)
        });

        //sending welcome email
        const mailOptions = {
            from: process.env.SENDER_EMAIL,
            to: email,
            subject: 'Welcome to Laos',
            text: `Welcome to laos website. Your account has been created with email id: ${email}`
        }

        await transporter.sendMail(mailOptions);

        return res.json({success: true}); //user is successfully registered

    } catch (error) {
        res.json({success: false, message: error.message})
    }
}

export const login = async (req, res)=>{
    const {email, password} = req.body;

    //validate email and password

    if(!email || !password){
        return res.json({success: false, message: 'Email and password are required'})
    }

    try {
        
        const user = await userModel.findOne({email});

        if(!user){
            return res.json({success: false, message: 'Invalid email'})
        }

        //compare the password the user has provided and the one stored in the mongodb database
        const isMatch = await bcrypt.compare(password, user.password);

        if(!isMatch){
            return res.json({success: false, message: 'Invalid password'})
        }

        const token = jwt.sign({id: user._id}, process.env.JWT_SECRET, {expiresIn: '7d'}); //7 days

        res.cookie('token', token, {
            httpOnly: true, //only http can access this cookie
            secure: process.env.NODE_ENV === 'production',
            sameSite: process.env.NODE_ENV === 'production' ? 'none' : 'strict',
            maxAge: 7*24*60*60*1000 //expiry time in milliseconds (converted from 7 days)
        });

        return res.json({success: true}); //user is successfully logged in

    } catch (error) {
        return res.json({success: false, message: error.message});
    }
}

export const logout = async (req, res)=>{
    try {
        res.clearCookie('token', {
            httpOnly: true, //only http can access this cookie
            secure: process.env.NODE_ENV === 'production',
            sameSite: process.env.NODE_ENV === 'production' ? 'none' : 'strict',
        })

        return res.json({success: true, message: "Logged Out"}) //user is successfully logged out

    } catch (error) {
        return res.json({success: false, message: error.message});
    }
}

//send verification OTP to the user's email (verify email using otp)
export const sendVerifyOtp = async(req, res)=>{
    try {

        const userId = req.userId; //get it from the middleware

        const user= await userModel.findById(userId);

        if(user.isAccountVerified){
            return res.json({success: false, message: "Account already verified"})
        }

        //It'll generate a six digit random number and we'll convert it into string then store it in a variable
        const otp = String(Math.floor(100000 + Math.random()*900000));

        user.verifyOtp = otp;
        user.verifyOtpExpireAt = Date.now() + 24 * 60 * 60* 1000 //one day from now (in milliseconds)

        await user.save();

        const mailOption = {
            from: process.env.SENDER_EMAIL,
            to: user.email,
            subject: 'Account Verification OTP',
            //text: `Your OTP is ${otp}. Verify your account using this OTP`,
            html: EMAIL_VERIFY_TEMPLATE.replace("{{otp}}", otp).replace().replace("{{email}}", user.email)
        }

        await transporter.sendMail(mailOption);

        res.json({success: true, message: 'Verification OTP sent on email'});

    } catch (error) {
        res.json({success: false, message: error.message});
    }
}

export const verifyEmail = async(req, res)=>{
    const userId = req.userId; //get it from the middleware
    const { otp } = req.body;

    if(!userId || !otp){
        return res.json({success: false, message: 'Missing Details'});
    }

    try {
        
        const user = await userModel.findById(userId);

        if(!user){
            return res.json({success: false, message: 'User not found'});
        }

        if(user.verifyOtp === '' || user.verifyOtp !== otp){
            return res.json({success: false, message: 'Invalid OTP'});
        }

        if(user.verifyOtpExpireAt < Date.now()){
            return res.json({success: false, message: 'OTP Expired'});
        }

        //after validating everything, we verify the user account
        user.isAccountVerified = true;
        user.verifyOtp = '';
        user.verifyOtpExpireAt = 0;

        await user.save(); //save the user data

        return res.json({success: true, message: 'Email verified successfully'})

    } catch (error) {
        return res.json({success: false, message: error.message});
    }
}

//check if user is authenticated
export const isAuthenticated = async (req, res)=>{
    try {

        //execute the middleware first

        return res.json({success: true});
        
    } catch (error) {
        return res.json({success: false, message: error.message});
    }
}

//send password reset OTP
export const sendResetOtp = async(req, res)=>{
    const {email} = req.body;

    if(!email){
        return res.json({success: false, message: 'Email is required'});
    }

    try {

        const user = await userModel.findOne({email});
        if(!user){
            return res.json({success: false, message: 'User not found'});
        }

        const otp = String(Math.floor(100000 + Math.random()*900000));

        user.resetOtp = otp;
        user.resetOtpExpireAt = Date.now() +  15 * 60* 1000 //15 minutes from now (in milliseconds)

        await user.save(); //save the user

        const mailOption = {
            from: process.env.SENDER_EMAIL,
            to: user.email,
            subject: 'Password reset OTP',
            //text: `Your OTP for resetting your password is ${otp}. Use this OTP to proceed with resetting your password.`
            html: PASSWORD_RESET_TEMPLATE.replace("{{otp}}", otp).replace("{{email}}, user.email")
        };

        await transporter.sendMail(mailOption);

        return res.json({success: true, message: 'OTP sent to your email'});
        
    } catch (error) {
        return res.json({success: false, message: error.message});
    }
}

// Reset user password
export const resetPassword = async (req, res)=>{

    const {email, otp, newPassword} = req.body;

    if(!email || !otp || !newPassword){
        return res.json({success: false, message: 'Email, OTP and new password are required'});
    }

    try {

        const user = await userModel.findOne({email});

        if(!user){
            return res.json({success: false, message: 'User not found'});
        }

        if(user.resetOtp === "" || user.resetOtp !== otp){
            return res.json({success: false, message: 'Invalid OTP'});
        }

        if(user.resetOtpExpireAt < Date.now()){
            return res.json({success: false, message: 'OTP Expired'});
        }

        //first we encrypt the password
        const hashedPassword = await bcrypt.hash(newPassword,10);

        user.password = hashedPassword;
        user.resetOtp = '';
        user.resetOtpExpireAt = 0;

        await user.save();

        return res.json({success: true, message: 'Password has been reset successfully'});
        
    } catch (error) {
        return res.json({success: false, message: error.message});
    }
}