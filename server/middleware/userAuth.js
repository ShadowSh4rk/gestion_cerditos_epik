import jwt from "jsonwebtoken";

const userAuth = async(req, res, next) =>{
    const {token} = req.cookies;

    if(!token){
        return res.json({success: false, message: 'Not authorized. Login again'})
    }

    try {

        //first we decode that we're getting from req.cookies
        const tokenDecode = jwt.verify(token, process.env.JWT_SECRET);

        if(tokenDecode.id){
            //if it has de id:
            req.userId = tokenDecode.id
        }else{
            return res.json({success: false, message: 'Not authorized. Login again'});
        }

        next();
        
    } catch (error) {
        return res.json({success: false, message: error.message});
    }
}

export default userAuth;